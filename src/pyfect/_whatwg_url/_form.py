"""``application/x-www-form-urlencoded`` parsing and serializing, as
``URLSearchParams`` does them."""

from __future__ import annotations

from collections.abc import Iterable

from pyfect._js import to_well_formed
from pyfect._whatwg_url import _percent


def parse(text: str) -> list[tuple[str, str]]:
    """The name-value pairs of ``text``: ``&``-separated, ``+`` a space,
    ``%XX`` decoded as UTF-8 (invalid bytes become U+FFFD)."""
    pairs: list[tuple[str, str]] = []
    for sequence in text.split("&"):
        if sequence == "":
            continue
        name, _, value = sequence.partition("=")
        pairs.append((_decode(name), _decode(value)))
    return pairs


def _decode(text: str) -> str:
    return _percent.decode(text.replace("+", " ")).decode("utf-8", "replace")


def serialize(pairs: Iterable[tuple[str, str]]) -> str:
    return "&".join(f"{_encode(name)}={_encode(value)}" for name, value in pairs)


def _encode(text: str) -> str:
    """As a JavaScript string becomes a ``USVString``, a lone surrogate is
    U+FFFD."""
    return _percent.encode(to_well_formed(text), _percent.FORM, space_as_plus=True)
