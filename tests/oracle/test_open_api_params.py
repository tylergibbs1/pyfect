"""OpenAPI parameters of number schemas, as Effect v4 prints them under Node
(``OpenApi.fromApi`` on ``params: {id: Schema.Int}``, ``query: {limit:
optionalKey(Int), n: Number, f: Finite}``). DOGFOOD B13 asked whether an
``S.Int`` path parameter documented as a string with a number pattern is
right: it is what Effect writes (params are string-encoded), so it is pinned."""

from typing import Any

from pyfect import schema as S
from pyfect.http_api import HttpApi, HttpApiGroup, endpoint, openapi

from ._http_api import struct

_NUMBER_STRING: dict[str, Any] = {
    "type": "string",
    "pattern": r"^[+-]?(?:\d+(?:\.\d+)?|\.\d+)(?:[Ee][+-]?\d+)?$",
}


class _Group(HttpApiGroup, identifier="g"):
    a = endpoint.get(
        "a",
        "/m/:id",
        params=struct({"id": S.Int}),
        query=struct({"limit": S.Int, "n": S.Number, "f": S.Finite}, optional=["limit"]),
        success=S.String,
    )


def test_number_params_and_query_are_documented_as_effect_documents_them():
    spec = openapi.from_api(HttpApi.make("x").add(_Group))
    assert spec["paths"]["/m/{id}"]["get"]["parameters"] == [
        {"name": "id", "in": "path", "schema": _NUMBER_STRING, "required": True},
        {"name": "limit", "in": "query", "schema": _NUMBER_STRING, "required": False},
        {
            "name": "n",
            "in": "query",
            "schema": {
                "anyOf": [
                    _NUMBER_STRING,
                    {"type": "string", "enum": ["Infinity", "-Infinity", "NaN"]},
                ]
            },
            "required": True,
        },
        {"name": "f", "in": "query", "schema": _NUMBER_STRING, "required": True},
    ]
