"""URLs (Effect's ``Url``): parsing and immutable updates of a ``Url``.

A ``Url`` is JavaScript's ``URL`` as an immutable Python value, parsed and
normalized by the WHATWG URL Standard as Node parses it::

    url = from_string("HTTPS://Example.com:443/a/../b c").unwrap()
    url.href   # "https://example.com/b%20c"

Each setter runs ``URL``'s setter of the same name on a copy and gives the
copy back; ``mutate`` hands a ``MutableUrl`` copy to a function.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from pyfect._url import Url
from pyfect._whatwg_url import UrlRecord, form, setters
from pyfect.errors import IllegalArgumentError, TaggedError
from pyfect.http import url_params as _params
from pyfect.redacted import Redacted
from pyfect.redacted import value as redacted_value
from pyfect.result import Err, Ok, Result


def parse(text: str, base: str | Url | None = None) -> Url:
    """``new URL(text, base)``; raises ``ValueError`` when ``text`` is not
    a URL."""
    return Url(text, base)


def href(url: Url) -> str:
    return url.href


def origin(url: Url) -> str:
    """``url.origin``: ``scheme://host[:port]`` for ``http(s)``, ``ws(s)``
    and ``ftp`` URLs, ``"null"`` for the others."""
    return url.origin


@dataclass(eq=False)
class UrlError(TaggedError):
    """A request's URL could not be built."""

    cause: object


def _append_params(record: UrlRecord, params: _params.UrlParams) -> UrlRecord:
    """``searchParams.append`` of each pair: the query rewritten as
    ``URLSearchParams`` writes it."""
    pairs = [*form.parse(record.query or ""), *((k, _params.unwrap(v)) for k, v in params)]
    return setters.set_query(record, form.serialize(pairs))


def make(url: str, params: _params.UrlParams, hash: str | None) -> Result[Url, UrlError]:
    """``url`` with ``params`` appended to its query and ``hash`` (when
    given) as its fragment."""
    parsed = Url.parse(url)
    if parsed is None:
        return Err(UrlError(ValueError(f"Invalid URL: {url!r}")))
    record = parsed.record
    if params.params:
        record = _append_params(record, params)
    if hash is not None:
        record = setters.set_hash(record, hash)
    return Ok(Url.from_record(record))


def from_string(url: str, base: str | Url | None = None) -> Result[Url, IllegalArgumentError]:
    parsed = Url.parse(url, base)
    if parsed is not None:
        return Ok(parsed)
    suffix = "" if base is None else f' with base "{base}"'
    return Err(IllegalArgumentError(f'Invalid URL: "{url}"{suffix}'))


class MutableUrl:
    """A copy of a ``Url`` whose attributes can be set, as a JavaScript
    ``URL``'s can (``mutate`` hands one out). Setting ``href`` to text that
    is not a URL raises ``ValueError``, as ``URL`` throws."""

    __slots__ = ("record",)

    def __init__(self, url: Url) -> None:
        self.record: UrlRecord = url.record

    def freeze(self) -> Url:
        return Url.from_record(self.record)

    def _get(self) -> Url:
        return Url.from_record(self.record)

    @property
    def href(self) -> str:
        return self._get().href

    @href.setter
    def href(self, value: str) -> None:
        self.record = parse(value).record

    @property
    def protocol(self) -> str:
        return self._get().protocol

    @protocol.setter
    def protocol(self, value: str) -> None:
        self.record = setters.set_protocol(self.record, value)

    @property
    def username(self) -> str:
        return self.record.username

    @username.setter
    def username(self, value: str) -> None:
        self.record = setters.set_username(self.record, value)

    @property
    def password(self) -> str:
        return self.record.password

    @password.setter
    def password(self, value: str) -> None:
        self.record = setters.set_password(self.record, value)

    @property
    def host(self) -> str:
        return self._get().host

    @host.setter
    def host(self, value: str) -> None:
        self.record = setters.set_host(self.record, value)

    @property
    def hostname(self) -> str:
        return self._get().hostname

    @hostname.setter
    def hostname(self, value: str) -> None:
        self.record = setters.set_hostname(self.record, value)

    @property
    def port(self) -> str:
        return self._get().port

    @port.setter
    def port(self, value: str | int) -> None:
        self.record = setters.set_port(self.record, str(value))

    @property
    def pathname(self) -> str:
        return self.record.pathname

    @pathname.setter
    def pathname(self, value: str) -> None:
        self.record = setters.set_pathname(self.record, value)

    @property
    def search(self) -> str:
        return self._get().search

    @search.setter
    def search(self, value: str) -> None:
        self.record = setters.set_search(self.record, value)

    @property
    def hash(self) -> str:
        return self._get().hash

    @hash.setter
    def hash(self, value: str) -> None:
        self.record = setters.set_hash(self.record, value)

    @property
    def origin(self) -> str:
        return self.record.origin()

    def __repr__(self) -> str:
        return f"MutableUrl({self.href!r})"


def mutate(url: Url, f: Callable[[MutableUrl], object]) -> Url:
    """``url`` changed by ``f`` on a mutable copy."""
    copy = MutableUrl(url)
    f(copy)
    return copy.freeze()


def _set(url: Url, update: Callable[[UrlRecord], UrlRecord]) -> Url:
    return Url.from_record(update(url.record))


def set_hash(url: Url, hash: str) -> Url:
    return _set(url, lambda r: setters.set_hash(r, hash))


def set_host(url: Url, host: str) -> Url:
    return _set(url, lambda r: setters.set_host(r, host))


def set_hostname(url: Url, hostname: str) -> Url:
    return _set(url, lambda r: setters.set_hostname(r, hostname))


def set_href(url: Url, href: str) -> Url:
    """``href`` parsed; raises ``ValueError`` when it is not a URL, as
    ``URL``'s ``href`` setter throws."""
    return parse(href)


def set_password(url: Url, password: str | Redacted[str]) -> Url:
    plain = password if isinstance(password, str) else redacted_value(password)
    return _set(url, lambda r: setters.set_password(r, plain))


def set_username(url: Url, username: str) -> Url:
    return _set(url, lambda r: setters.set_username(r, username))


def set_pathname(url: Url, pathname: str) -> Url:
    return _set(url, lambda r: setters.set_pathname(r, pathname))


def set_port(url: Url, port: str | int) -> Url:
    return _set(url, lambda r: setters.set_port(r, str(port)))


def set_protocol(url: Url, protocol: str) -> Url:
    """A new scheme; switching between a special scheme (``http``, ...) and
    another is ignored, as ``URL`` ignores it."""
    return _set(url, lambda r: setters.set_protocol(r, protocol))


def set_search(url: Url, search: str) -> Url:
    return _set(url, lambda r: setters.set_search(r, search))


def url_params(url: Url) -> _params.UrlParams:
    return _params.UrlParams(url.search_params)


def set_url_params(url: Url, input: _params.Input) -> Url:
    return set_search(url, _params.to_string(input))


def modify_url_params(url: Url, f: Callable[[_params.UrlParams], _params.Input]) -> Url:
    return set_url_params(url, f(url_params(url)))


__all__ = [
    "MutableUrl",
    "Url",
    "UrlError",
    "from_string",
    "href",
    "make",
    "modify_url_params",
    "mutate",
    "origin",
    "parse",
    "set_hash",
    "set_host",
    "set_hostname",
    "set_href",
    "set_password",
    "set_pathname",
    "set_port",
    "set_protocol",
    "set_search",
    "set_url_params",
    "set_username",
    "url_params",
]
