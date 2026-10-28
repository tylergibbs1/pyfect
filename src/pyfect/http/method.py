"""HTTP methods (Effect's ``HttpMethod``)."""

from __future__ import annotations

from typing import Literal, TypeIs

type HttpMethod = Literal[
    "GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS", "TRACE", "QUERY"
]

type NoBody = Literal["GET", "HEAD", "OPTIONS", "TRACE"]
"""The methods whose requests carry no body."""

type WithBody = Literal["POST", "PUT", "DELETE", "PATCH", "QUERY"]

ALL: frozenset[HttpMethod] = frozenset(
    ("GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS", "TRACE", "QUERY")
)


def has_body(method: HttpMethod) -> TypeIs[WithBody]:
    """Whether requests with ``method`` send their body."""
    return method not in ("GET", "HEAD", "OPTIONS", "TRACE")


def is_http_method(value: object) -> TypeIs[HttpMethod]:
    return value in ALL


__all__ = ["ALL", "HttpMethod", "NoBody", "WithBody", "has_body", "is_http_method"]
