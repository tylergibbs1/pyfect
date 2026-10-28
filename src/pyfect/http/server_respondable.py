"""Values a server can turn into a response (Effect's
``HttpServerRespondable``).

A respondable defines ``__http_response__``, giving the response to send
when it is an error of a handler (``HttpServerError`` reasons, schema
errors, a ``HttpServerResponse`` itself)::

    @dataclass(eq=False)
    class Unauthorized(fx.TaggedError):
        def __http_response__(self):
            return succeed(server_response.empty(status=401))
"""

from __future__ import annotations

from typing import Any, Protocol, TypeIs, runtime_checkable

from pyfect._core import Effect
from pyfect.effect import succeed
from pyfect.errors import NoSuchElementException
from pyfect.http.server_response import HttpServerResponse, empty
from pyfect.schema import SchemaError


@runtime_checkable
class Respondable(Protocol):
    def __http_response__(self) -> Effect[HttpServerResponse, Any]: ...


def is_respondable(value: object) -> TypeIs[Respondable]:
    return isinstance(value, Respondable)


_BAD_REQUEST = empty(status=400)
_NOT_FOUND = empty(status=404)


def to_response(value: Respondable) -> Effect[HttpServerResponse]:
    """The response of ``value``; its failure is a defect."""
    if isinstance(value, HttpServerResponse):
        return succeed(value)
    return value.__http_response__().or_die()


def to_response_or_else(value: object, or_else: HttpServerResponse) -> Effect[HttpServerResponse]:
    """The response of a respondable (``or_else`` if making it fails), 400
    for a ``SchemaError``, 404 for a ``NoSuchElementException``, else
    ``or_else``."""
    if isinstance(value, HttpServerResponse):
        return succeed(value)
    if is_respondable(value):
        return value.__http_response__().catch_cause(lambda _: succeed(or_else))
    if isinstance(value, SchemaError):
        return succeed(_BAD_REQUEST)
    if isinstance(value, NoSuchElementException):
        return succeed(_NOT_FOUND)
    return succeed(or_else)


def to_response_or_else_defect(
    value: object, or_else: HttpServerResponse
) -> Effect[HttpServerResponse]:
    """``to_response_or_else`` for a defect: only respondables count."""
    if isinstance(value, HttpServerResponse):
        return succeed(value)
    if is_respondable(value):
        return value.__http_response__().catch_cause(lambda _: succeed(or_else))
    return succeed(or_else)


__all__ = [
    "Respondable",
    "is_respondable",
    "to_response",
    "to_response_or_else",
    "to_response_or_else_defect",
]
