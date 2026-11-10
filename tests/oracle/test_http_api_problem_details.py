"""Ports of Effect's ``httpapi/HttpApiProblemDetails.test.ts``: typed RFC 9457
problems (``error.Problem``), the ``ProblemDetails`` middleware and
``schema.as_problem``. Each test's docstring is the Effect test title,
prefixed by its ``describe`` blocks."""

# Groups made with ``HttpApiGroup.make`` type their endpoints as ``Any``.
# pyright: reportUnknownLambdaType=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false

import asyncio
from typing import Any

import pyfect as fx
from pyfect import effect, error_reporter, layer
from pyfect import schema as S
from pyfect.exit import Failure
from pyfect.http import router, server
from pyfect.http.web import WebRequest, WebResponse
from pyfect.http_api import builder, get_group, openapi
from pyfect.http_api import endpoint as ep
from pyfect.http_api import error as api_error
from pyfect.http_api import middleware as mw
from pyfect.http_api import schema as api_schema
from pyfect.http_api import test as api_test
from pyfect.http_api.api import HttpApi
from pyfect.http_api.group import HttpApiGroup
from pyfect.scope import scoped

from ._http_api import struct


def _fetch(app: Any, path: str, *around: Any) -> tuple[WebResponse, bytes]:
    """The response to ``GET path`` and its body (Effect's ``fetchWith``)."""

    async def main() -> tuple[WebResponse, bytes]:
        served = app.pipe(layer.provide(server.layer_services))
        for provided in around:
            served = served.pipe(layer.provide(provided))
        made = router.to_web_handler(served, disable_logger=True)
        try:
            response = await made.handler(WebRequest(f"http://localhost{path}"))
            return response, await response.read()
        finally:
            await made.dispose()

    return asyncio.run(main())


def _json(body: bytes) -> object:
    import json

    return json.loads(body)


def _client_call(api: Any, group: Any, live: Any, call: Any) -> Any:
    def program() -> Any:
        client = yield from api_test.groups(api, [group]).pipe(fx.provide(live))
        return (yield from call(get_group(client, group)).flip())

    return fx.run_blocking(scoped(effect.gen(program)).pipe(fx.provide(server.layer_services)))


class OutOfCredit(
    api_error.Problem,
    type="https://example.com/probs/out-of-credit",
    status=403,
    title="You do not have enough credit.",
):
    balance: float


_PURCHASE = HttpApiGroup.make("test").add(
    ep.get("purchase", "/purchase", success=S.String, error=OutOfCredit)
)
_PURCHASE_API = HttpApi.make("Api").add(_PURCHASE)
_PURCHASE_LIVE = builder.group(
    _PURCHASE_API,
    _PURCHASE,
    lambda h: h.handle(_PURCHASE.endpoints["purchase"])(
        lambda _: effect.fail(OutOfCredit(balance=30))
    ),
)


def test_responds_with_the_declared_status_and_a_problem_json_body() -> None:
    """HttpApiError.Problem / responds with the declared status and a problem+json body"""
    response, body = _fetch(
        builder.layer(_PURCHASE_API).pipe(layer.provide(_PURCHASE_LIVE)), "/purchase"
    )
    assert response.status == 403
    assert response.get("content-type") == "application/problem+json"
    assert _json(body) == {
        "type": "https://example.com/probs/out-of-credit",
        "status": 403,
        "title": "You do not have enough credit.",
        "balance": 30,
    }


def test_decodes_the_response_into_the_class_instance() -> None:
    """HttpApiError.Problem / client / decodes the response into the class instance"""
    error = _client_call(_PURCHASE_API, _PURCHASE, _PURCHASE_LIVE, lambda c: c.method("purchase")())
    assert isinstance(error, OutOfCredit)
    assert error._tag == "OutOfCredit"  # pyright: ignore[reportPrivateUsage]
    assert error.balance == 30


def test_lists_application_problem_json_under_the_status_in_the_openapi_spec() -> None:
    """HttpApiError.Problem / lists application/problem+json under the status in the OpenAPI spec"""
    content = openapi.from_api(_PURCHASE_API)["paths"]["/purchase"]["get"]["responses"]["403"][
        "content"
    ]
    assert "application/problem+json" in content


def test_discriminates_decoding_by_type_and_keeps_the_declared_status() -> None:
    """HttpApiError.Problem / discriminates decoding by type and keeps the declared status"""

    class Banned(
        api_error.Problem,
        type="https://example.com/probs/banned",
        status=403,
        title="You are banned.",
    ):
        balance: float

    body = {
        "type": "https://example.com/probs/banned",
        "status": 999,
        "title": "wire",
        "balance": 1,
    }
    assert isinstance(S.decode_unknown_exit(OutOfCredit)(body), Failure)
    decoded = S.decode_unknown_sync(S.Union(OutOfCredit, Banned))(body)
    assert isinstance(decoded, Banned)
    assert decoded.status == 403


def test_problem_fixed_members_and_message() -> None:
    """A Problem's ``type``, ``status`` and ``title`` are not fields of its own; its message
    is ``detail`` or ``title``, and errors below 500 are not reported (Effect's
    ``ErrorReporter.ignore``)."""
    assert str(OutOfCredit(balance=1)) == "You do not have enough credit."
    assert str(OutOfCredit(balance=1, detail="Top up")) == "Top up"
    assert OutOfCredit(balance=1).report_ignored
    assert not api_error.InternalServerErrorProblem().report_ignored
    try:

        class Bad(  # pyright: ignore[reportUnusedClass]
            api_error.Problem, type="about:blank", status=400, title="Bad"
        ):
            status: int  # pyright: ignore[reportGeneralTypeIssues]

    except TypeError as error:
        assert "status" in str(error)
    else:
        raise AssertionError("expected a TypeError")


_LIST = HttpApiGroup.make("test").add(
    ep.get("list", "/list", query=struct({"page": S.String}), success=S.String)
)
_PLAIN_API = HttpApi.make("Api").add(_LIST)
_PROBLEM_API = HttpApi.make("Api").add(_LIST).middleware(mw.ProblemDetails)


def _list_live(api: Any) -> Any:
    return builder.group(
        api, _LIST, lambda h: h.handle(_LIST.endpoints["list"])(lambda _: effect.succeed("ok"))
    )


def test_keeps_the_empty_400_without_the_middleware() -> None:
    """HttpApiMiddleware.ProblemDetails / keeps the empty 400 without the middleware"""
    response, body = _fetch(
        builder.layer(_PLAIN_API).pipe(layer.provide(_list_live(_PLAIN_API))), "/list"
    )
    assert response.status == 400
    assert body == b""


def test_renders_a_generic_problem_json_400_without_details() -> None:
    """HttpApiMiddleware.ProblemDetails / renders a generic problem+json 400 without details"""
    app = (
        builder.layer(_PROBLEM_API)
        .pipe(layer.provide(_list_live(_PROBLEM_API)))
        .pipe(layer.provide(mw.layer_problem_details()))
    )
    response, body = _fetch(app, "/list")
    assert response.status == 400
    assert response.get("content-type") == "application/problem+json"
    assert _json(body) == {
        "type": "about:blank",
        "title": "Bad Request",
        "status": 400,
        "detail": "Request validation failed",
    }


def test_adds_errors_prefixed_with_the_slot_name_when_include_details_is_enabled() -> None:
    """HttpApiMiddleware.ProblemDetails / adds errors prefixed with the slot name when includeDetails is enabled"""  # noqa: E501
    app = (
        builder.layer(_PROBLEM_API)
        .pipe(layer.provide(_list_live(_PROBLEM_API)))
        .pipe(layer.provide(mw.layer_problem_details(include_details=True)))
    )
    response, body = _fetch(app, "/list")
    assert response.status == 400
    decoded = S.decode_unknown_sync(api_error.BadRequestProblem)(_json(body))
    assert decoded.errors is not None
    assert decoded.errors[0]["path"][0] == "query"
    assert isinstance(decoded.errors[0]["message"], str)


def test_adds_a_problem_json_400_to_the_openapi_spec() -> None:
    """HttpApiMiddleware.ProblemDetails / adds a problem+json 400 to the OpenAPI spec"""
    assert "400" not in openapi.from_api(_PLAIN_API)["paths"]["/list"]["get"]["responses"]
    responses = openapi.from_api(_PROBLEM_API)["paths"]["/list"]["get"]["responses"]
    assert "application/problem+json" in responses["400"]["content"]


_COUNT = HttpApiGroup.make("test").add(ep.get("count", "/count", success=S.Number))
_ENCODE_API = HttpApi.make("Api").add(_COUNT).middleware(mw.ProblemDetails)
_ENCODE_LIVE = builder.group(
    _ENCODE_API,
    _COUNT,
    lambda h: h.handle(_COUNT.endpoints["count"])(lambda _: effect.succeed("not a number")),
)


def test_renders_a_generic_problem_json_500_and_reports_the_schema_error_once() -> None:
    """HttpApiMiddleware.ProblemDetails / response encoding failure / renders a generic problem+json 500 and reports the schema error once"""  # noqa: E501
    reports: list[error_reporter.Report] = []
    reporter = error_reporter.make(reports.append)
    app = (
        builder.layer(_ENCODE_API)
        .pipe(layer.provide(_ENCODE_LIVE))
        .pipe(layer.provide(mw.layer_problem_details(include_details=True)))
    )
    response, body = _fetch(app, "/count", error_reporter.layer([reporter]))
    assert response.status == 500
    assert response.get("content-type") == "application/problem+json"
    assert _json(body) == {"type": "about:blank", "title": "Internal Server Error", "status": 500}
    assert len(reports) == 1
    reported = reports[0].cause.squash()
    assert isinstance(reported, api_error.HttpApiSchemaError)
    assert reported.kind == "Body"


def test_decodes_the_500_into_internal_server_error_problem() -> None:
    """HttpApiMiddleware.ProblemDetails / response encoding failure / client / decodes the 500 into InternalServerErrorProblem"""  # noqa: E501
    live = _ENCODE_LIVE.pipe(layer.provide_merge(mw.layer_problem_details()))
    error = _client_call(_ENCODE_API, _COUNT, live, lambda c: c.method("count")())
    assert isinstance(error, api_error.InternalServerErrorProblem)


def test_adds_a_problem_json_500_to_the_openapi_spec() -> None:
    """HttpApiMiddleware.ProblemDetails / response encoding failure / adds a problem+json 500 to the OpenAPI spec"""  # noqa: E501
    responses = openapi.from_api(_ENCODE_API)["paths"]["/count"]["get"]["responses"]
    assert "application/problem+json" in responses["500"]["content"]


def test_encodes_a_built_in_error_as_a_problem() -> None:
    """HttpApiSchema.asProblem / encodes a built-in error as a problem"""
    group = HttpApiGroup.make("test").add(
        ep.get(
            "user",
            "/user",
            success=S.String,
            error=api_error.NotFound.pipe(api_schema.as_problem(title="Not Found")),
        )
    )
    api = HttpApi.make("Api").add(group)
    live = builder.group(
        api,
        group,
        lambda h: h.handle(group.endpoints["user"])(lambda _: effect.fail(api_error.NotFound())),
    )
    response, body = _fetch(builder.layer(api).pipe(layer.provide(live)), "/user")
    assert response.status == 404
    assert response.get("content-type") == "application/problem+json"
    assert _json(body) == {"type": "about:blank", "title": "Not Found", "status": 404}


def test_rejects_a_body_with_a_different_type() -> None:
    """HttpApiSchema.asProblem / rejects a body with a different type"""
    schema = api_error.NotFound.pipe(api_schema.as_problem(title="Not Found"))
    exit_ = S.decode_unknown_exit(schema)(
        {"type": "https://example.com/probs/other", "title": "Not Found", "status": 404}
    )
    assert isinstance(exit_, Failure)
