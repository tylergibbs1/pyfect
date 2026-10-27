"""Case conversion: the case functions of Effect's ``String`` module.

The word-based converters split their input into words at case changes
(``"camelCase"``, ``"CAMELCase"``), letter/digit boundaries and any run of
characters other than ASCII letters and digits, then join the words again::

    case.snake_case("helloWorld")     # "hello_world"
    case.camel_case("hello world")    # "helloWorld"
    case.constant_case("api-v2 xml")  # "API_V_2_XML"
    case.config_case("api-v2 xml")    # "API_V2_XML" (digit groups kept)

The ``snake_to_*``, ``*_to_snake`` and ``kebab_to_snake`` functions only
swap separators or split at capitals, for input known to be in that case.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence

type Patterns = re.Pattern[str] | Sequence[re.Pattern[str]]
"""A pattern or several, applied in order. Each replaces every match."""

# Camel case ("camelCase" -> "camel Case", "CAMELCase" -> "CAMEL Case") and
# digit boundaries ("camel2case" -> "camel 2 case").
_SPLIT = (
    re.compile(r"([a-z0-9])([A-Z])"),
    re.compile(r"([A-Z])([A-Z][a-z])"),
    re.compile(r"([A-Za-z])([0-9])"),
    re.compile(r"([0-9])([A-Za-z])"),
)
# Config paths keep digit groups such as "v2".
_CONFIG_SPLIT = _SPLIT[:2]
_STRIP = re.compile(r"[^A-Za-z0-9]+")
_CAPITAL = re.compile(r"([A-Z])")


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
    split: Patterns = _SPLIT,
    strip: Patterns = _STRIP,
    delimiter: str = " ",
    transform: Callable[[str], str] = str.lower,
) -> str:
    """The words of ``text``, each through ``transform``, joined by
    ``delimiter`` (``no_case("helloWorld")`` is ``"hello world"``).

    Each ``split`` pattern has two groups, and a word boundary goes between
    them; each match of a ``strip`` pattern becomes a boundary. Unlike a
    JavaScript regex without the ``g`` flag, a pattern replaces every match.
    """
    words = _words(text, _patterns(split), _patterns(strip))
    return delimiter.join(transform(word) for word in words)


def _capitalized(word: str) -> str:
    return word[:1].upper() + word[1:].lower()


def pascal_case(text: str) -> str:
    """``"hello world"`` -> ``"HelloWorld"``."""
    return no_case(text, delimiter="", transform=_capitalized)


def camel_case(text: str) -> str:
    """``"hello world"`` -> ``"helloWorld"``."""
    words = _words(text, _SPLIT, (_STRIP,))
    return "".join(w.lower() if i == 0 else _capitalized(w) for i, w in enumerate(words))


def constant_case(text: str) -> str:
    """``"hello world"`` -> ``"HELLO_WORLD"``; digits split off
    (``"api-v2"`` -> ``"API_V_2"``)."""
    return no_case(text, delimiter="_", transform=str.upper)


def config_case(text: str) -> str:
    """CONSTANT_CASE that keeps digit groups (``"api-v2 xml"`` ->
    ``"API_V2_XML"``), as configuration keys are written. Not idempotent:
    ``"field2value"`` gives ``"FIELD2VALUE"``, which gives ``"FIELD2_VALUE"``."""
    return "_".join(word.upper() for word in _words(text, _CONFIG_SPLIT, (_STRIP,)))


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
