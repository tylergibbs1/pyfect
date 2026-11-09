"""``Url``, the URL value every pyfect API takes and gives back: JavaScript's
``URL`` as a Python value, parsed by the WHATWG URL Standard (``Url(text)``
is ``new URL(text)``, ``Url.can_parse`` is ``URL.canParse``) with the same
getters, immutable, equal and hashed by its ``href``."""

from __future__ import annotations

from typing import Self, final

from pyfect._js import to_well_formed
from pyfect._whatwg_url import UrlRecord, form, parse


def _parse(text: str, base: str | Url | None) -> UrlRecord | None:
    if base is None:
        base_record = None
    else:
        base_record = base.record if isinstance(base, Url) else parse(to_well_formed(base))
        if base_record is None:
            return None
    return parse(to_well_formed(text), base_record)


@final
class Url:
    """A URL, as ``new URL(text, base)`` parses it; raises ``ValueError``
    when ``text`` is not a URL. ``str(url)`` is its ``href``, so
    ``f"{url}/items"`` builds a URL text. Two URLs are equal when their
    ``href`` is, as Effect's ``Equal`` compares URLs.

    ``http.url`` has Effect's functions over it (``set_hash``, ``mutate``,
    ...)."""

    __slots__ = ("_href", "record")

    record: UrlRecord
    _href: str

    def __init__(self, text: str, base: str | Url | None = None) -> None:
        record = _parse(text, base)
        if record is None:
            suffix = "" if base is None else f" with base {str(base)!r}"
            raise ValueError(f"Invalid URL: {text!r}{suffix}")
        object.__setattr__(self, "record", record)
        object.__setattr__(self, "_href", record.href())

    @classmethod
    def from_record(cls, record: UrlRecord) -> Self:
        url = cls.__new__(cls)
        object.__setattr__(url, "record", record)
        object.__setattr__(url, "_href", record.href())
        return url

    @classmethod
    def parse(cls, text: str, base: str | Url | None = None) -> Url | None:
        """``URL.parse``: the URL, or ``None`` when ``text`` is not one."""
        record = _parse(text, base)
        return None if record is None else cls.from_record(record)

    @staticmethod
    def can_parse(text: str, base: str | Url | None = None) -> bool:
        """``URL.canParse``."""
        return _parse(text, base) is not None

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError(f"Url is immutable; http.url.set_{name} gives a new one")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("Url is immutable")

    def __reduce__(self) -> tuple[type[Url], tuple[str]]:
        return (Url, (self._href,))

    def __str__(self) -> str:
        return self._href

    def __repr__(self) -> str:
        return f"Url({self._href!r})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Url):
            return NotImplemented
        return self._href == other._href

    def __hash__(self) -> int:
        return hash(self._href)

    @property
    def href(self) -> str:
        return self._href

    @property
    def protocol(self) -> str:
        """The scheme and ``:`` (``"https:"``)."""
        return f"{self.record.scheme}:"

    @property
    def username(self) -> str:
        return self.record.username

    @property
    def password(self) -> str:
        return self.record.password

    @property
    def host(self) -> str:
        """The host and the port, if any (``"example.com:8080"``)."""
        record = self.record
        if record.host is None:
            return ""
        return record.host if record.port is None else f"{record.host}:{record.port}"

    @property
    def hostname(self) -> str:
        return self.record.host or ""

    @property
    def port(self) -> str:
        """The port, ``""`` when it is absent or the scheme's default."""
        return "" if self.record.port is None else str(self.record.port)

    @property
    def pathname(self) -> str:
        return self.record.pathname

    @property
    def search(self) -> str:
        """``?`` and the query, ``""`` when it is absent or empty."""
        query = self.record.query
        return f"?{query}" if query else ""

    @property
    def hash(self) -> str:
        """``#`` and the fragment, ``""`` when it is absent or empty."""
        fragment = self.record.fragment
        return f"#{fragment}" if fragment else ""

    @property
    def origin(self) -> str:
        return self.record.origin()

    @property
    def search_params(self) -> tuple[tuple[str, str], ...]:
        """The query's name-value pairs, as ``url.searchParams`` reads them
        (``http.url.url_params`` gives them as ``UrlParams``)."""
        return tuple(form.parse(self.record.query or ""))

    def to_json(self) -> str:
        """``URL.toJSON``: the ``href``."""
        return self._href
