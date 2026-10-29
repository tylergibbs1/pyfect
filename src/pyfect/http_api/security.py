"""Where a request carries its credentials (Effect's ``HttpApiSecurity``):
an ``Authorization`` scheme (``bearer``, ``http(scheme=...)``), HTTP Basic
(``basic``) or an API key in a header, query parameter or cookie
(``api_key``). A security middleware decodes them with
``HttpApiBuilder.security_decode``; OpenAPI documents them."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any, Literal, Self

from pyfect.context import Context, TagLike
from pyfect.redacted import Redacted


@dataclass(frozen=True, slots=True)
class Credentials:
    """HTTP Basic credentials."""

    username: str
    password: Redacted[str]


@dataclass(frozen=True, slots=True)
class _Security:
    annotations: Context[Any] = field(default_factory=Context.empty, kw_only=True)

    def annotate[S, T](self, tag: TagLike[S, T], value: S) -> Self:
        """This security with an annotation (``OpenApi.Description``, ...)."""
        return replace(self, annotations=self.annotations.add(tag, value))

    def annotate_merge(self, annotations: Context[Any]) -> Self:
        return replace(self, annotations=self.annotations.merge(annotations))

    def pipe[B](self, f: Callable[[Self], B], /) -> B:
        return f(self)


@dataclass(frozen=True, slots=True)
class Http(_Security):
    """An ``Authorization: <scheme> <credential>`` header; the credential
    is a ``Redacted`` string (empty when absent)."""

    scheme: str


@dataclass(frozen=True, slots=True)
class ApiKey(_Security):
    """An API key named ``key`` in a header (case-insensitive), query
    parameter or cookie; the credential is a ``Redacted`` string."""

    key: str
    in_: Literal["header", "query", "cookie"] = "header"


@dataclass(frozen=True, slots=True)
class Basic(_Security):
    """HTTP Basic: the credential is ``Credentials`` (empty when absent)."""


type HttpApiSecurity = Http | ApiKey | Basic
type Credential = Redacted[str] | Credentials
"""What decoding a security gives: ``Credentials`` for ``Basic``, else a
``Redacted`` string."""


def http(*, scheme: str) -> Http:
    return Http(scheme)


bearer: Http = http(scheme="Bearer")
basic: Basic = Basic()


def api_key(*, key: str, in_: Literal["header", "query", "cookie"] = "header") -> ApiKey:
    return ApiKey(key, in_)


__all__ = [
    "ApiKey",
    "Basic",
    "Credential",
    "Credentials",
    "Http",
    "HttpApiSecurity",
    "api_key",
    "basic",
    "bearer",
    "http",
]
