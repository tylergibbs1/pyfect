"""Case conversion and well-formedness: the case functions of Effect's
``String`` module, and its ``is_well_formed`` / ``to_well_formed``.

The word-based converters split their input into words at case changes
(``"camelCase"``, ``"CAMELCase"``, also in other scripts: ``"CaféÜber"``), letter/digit
boundaries and any run of characters other than Unicode letters, combining marks and
numbers, then join the words again. No Unicode normalization is applied::

    case.snake_case("helloWorld")     # "hello_world"
    case.camel_case("hello world")    # "helloWorld"
    case.constant_case("api-v2 xml")  # "API_V_2_XML"
    case.config_case("api-v2 xml")    # "API_V2_XML" (digit groups kept)

The ``snake_to_*``, ``*_to_snake`` and ``kebab_to_snake`` functions only
swap separators or split at capitals, for input known to be in that case.

A ``str`` can hold lone surrogates (from ``surrogateescape``, say), which
``str.encode()`` refuses. ``is_well_formed`` checks for them and
``to_well_formed`` replaces each with U+FFFD, as a UTF-8 encoder would::

    case.is_well_formed("a\\udc00b")  # False
    case.to_well_formed("a\\udc00b")  # "a\\ufffdb"
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from functools import cache

from pyfect import _js

type Patterns = re.Pattern[str] | Sequence[re.Pattern[str]]
"""A pattern or several, applied in order. Each replaces every match."""

_CAPITAL = re.compile(r"([A-Z])")


@cache
def _defaults() -> tuple[tuple[re.Pattern[str], ...], tuple[re.Pattern[str], ...], re.Pattern[str]]:
    """The word patterns, ``split``, ``config_split`` and ``strip``, compiled on first use
    (their Unicode classes are long), as Effect's ``\\p{L}``, ``\\p{M}`` and ``\\p{N}``
    patterns. Words are only split here, never read as numbers."""
    from pyfect._case_unicode import LETTER, LOWER, MARK, NUMBER, UPPER

    # Camel case ("camelCase" -> "camel Case", "CAMELCase" -> "CAMEL Case").
    lower_upper = re.compile(f"([{LOWER}{NUMBER}][{MARK}]*)([{UPPER}])")
    upper_upper = re.compile(f"([{UPPER}][{MARK}]*)([{UPPER}][{MARK}]*[{LOWER}])")
    # Digit boundaries ("camel2case" -> "camel 2 case"); config paths keep digit groups
    # such as "v2".
    split = (
        lower_upper,
        upper_upper,
        re.compile(f"([{LETTER}][{MARK}]*)([{NUMBER}])"),
        re.compile(f"([{NUMBER}][{MARK}]*)([{LETTER}])"),
    )
    return split, split[:2], re.compile(f"[^{LETTER}{MARK}{NUMBER}]+")


def _patterns(patterns: Patterns) -> Sequence[re.Pattern[str]]:
    return (patterns,) if isinstance(patterns, re.Pattern) else patterns


def _words(
    text: str, split: Sequence[re.Pattern[str]], strip: Sequence[re.Pattern[str]]
) -> list[str]:
    result = text
    for pattern in split:
        result = pattern.sub("\\1\0\\2", result)
    for pattern in strip:
        result = pattern.sub("\0", result)
    result = result.strip("\0")
    return result.split("\0") if result else []


def no_case(
    text: str,
    *,
    split: Patterns | None = None,
    strip: Patterns | None = None,
    delimiter: str = " ",
    transform: Callable[[str], str] = str.lower,
) -> str:
    """The words of ``text``, each through ``transform``, joined by
    ``delimiter`` (``no_case("helloWorld")`` is ``"hello world"``).

    Each ``split`` pattern has two groups, and a word boundary goes between
    them; each match of a ``strip`` pattern becomes a boundary. Unlike a
    JavaScript regex without the ``g`` flag, a pattern replaces every match.
    Left out, they are the converters' own patterns.
    """
    default_split, _, default_strip = _defaults()
    words = _words(
        text,
        default_split if split is None else _patterns(split),
        (default_strip,) if strip is None else _patterns(strip),
    )
    return delimiter.join(transform(word) for word in words)


def _capitalized(word: str) -> str:
    return word[:1].upper() + word[1:].lower()


def pascal_case(text: str) -> str:
    """``"hello world"`` -> ``"HelloWorld"``."""
    return no_case(text, delimiter="", transform=_capitalized)


def camel_case(text: str) -> str:
    """``"hello world"`` -> ``"helloWorld"``."""
    split, _, strip = _defaults()
    words = _words(text, split, (strip,))
    return "".join(w.lower() if i == 0 else _capitalized(w) for i, w in enumerate(words))


def constant_case(text: str) -> str:
    """``"hello world"`` -> ``"HELLO_WORLD"``; digits split off
    (``"api-v2"`` -> ``"API_V_2"``)."""
    return no_case(text, delimiter="_", transform=str.upper)


def config_case(text: str) -> str:
    """CONSTANT_CASE that keeps digit groups (``"api-v2 xml"`` ->
    ``"API_V2_XML"``), as configuration keys are written. Not idempotent:
    ``"field2value"`` gives ``"FIELD2VALUE"``, which gives ``"FIELD2_VALUE"``."""
    _, config_split, strip = _defaults()
    return "_".join(word.upper() for word in _words(text, config_split, (strip,)))


def kebab_case(text: str) -> str:
    """``"helloWorld"`` -> ``"hello-world"``."""
    return no_case(text, delimiter="-")


def snake_case(text: str) -> str:
    """``"helloWorld"`` -> ``"hello_world"``."""
    return no_case(text, delimiter="_")


def _from_snake(text: str, first: Callable[[str], str]) -> str:
    if not text or (len(text) % 2 == 0 and text.strip("_") == ""):
        return ""
    out = [first(text[0])]
    i = 1
    while i < len(text):
        if text[i] == "_":
            i += 1
            out.append(text[i : i + 1].upper())
        else:
            out.append(text[i])
        i += 1
    return "".join(out)


def snake_to_camel(text: str) -> str:
    """``"hello_world"`` -> ``"helloWorld"``: each ``_`` is dropped and
    the next character upper-cased."""
    return _from_snake(text, lambda c: c)


def snake_to_pascal(text: str) -> str:
    """``"hello_world"`` -> ``"HelloWorld"``."""
    return _from_snake(text, str.upper)


def snake_to_kebab(text: str) -> str:
    """Every ``_`` becomes ``-``."""
    return text.replace("_", "-")


def camel_to_snake(text: str) -> str:
    """``_`` before every capital, then lower case:
    ``"XMLHttpRequest"`` -> ``"_x_m_l_http_request"``."""
    return _CAPITAL.sub("_\\1", text).lower()


def pascal_to_snake(text: str) -> str:
    """``camel_to_snake`` that leaves the first character alone:
    ``"XMLHttpRequest"`` -> ``"x_m_l_http_request"``."""
    return (text[:1] + _CAPITAL.sub("_\\1", text[1:])).lower()


def kebab_to_snake(text: str) -> str:
    """Every ``-`` becomes ``_``."""
    return text.replace("-", "_")


def is_well_formed(text: str) -> bool:
    """Whether ``text`` has no lone surrogate, so it encodes as UTF-8
    without loss. A high surrogate followed by a low one counts as the
    character they pair into, as in a JavaScript string."""
    return _js.is_well_formed(text)


def to_well_formed(text: str) -> str:
    """``text`` with each lone surrogate replaced by U+FFFD; a surrogate
    pair becomes the character it encodes. Well-formed text is returned
    as is."""
    return _js.to_well_formed(text)


__all__ = [
    "Patterns",
    "camel_case",
    "camel_to_snake",
    "config_case",
    "constant_case",
    "is_well_formed",
    "kebab_case",
    "kebab_to_snake",
    "no_case",
    "pascal_case",
    "pascal_to_snake",
    "snake_case",
    "snake_to_camel",
    "snake_to_kebab",
    "snake_to_pascal",
    "to_well_formed",
]
