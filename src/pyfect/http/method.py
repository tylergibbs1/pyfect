"""HTTP methods (Effect's ``HttpMethod``)."""

from __future__ import annotations

from typing import Literal, TypeIs, overload

type HttpMethod = Literal[
    "GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS", "TRACE", "QUERY"
]

type NoBody = Literal["GET", "HEAD", "OPTIONS", "TRACE"]
"""The methods whose requests carry no body."""

type WithBody = Literal["POST", "PUT", "DELETE", "PATCH", "QUERY"]

ALL: frozenset[HttpMethod] = frozenset(
    ("GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS", "TRACE", "QUERY")
)


@overload
def has_body(method: HttpMethod) -> TypeIs[WithBody]: ...
@overload
def has_body(method: str) -> bool: ...
def has_body(method: str) -> bool:
    """Whether requests with ``method`` send their body. A method outside
    ``HttpMethod`` (a received ``PROPFIND``) can carry one, but is not
    narrowed."""
    return method not in ("GET", "HEAD", "OPTIONS", "TRACE")


def is_http_method(value: object) -> TypeIs[HttpMethod]:
    return value in ALL


__all__ = ["ALL", "HttpMethod", "NoBody", "WithBody", "has_body", "is_http_method"]
