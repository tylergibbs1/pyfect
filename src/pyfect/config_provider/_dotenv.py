"""``.env`` files: Effect's parser (the ``dotenv`` package's rules) and its
``dotenv-expand``-style ``$NAME`` / ``${NAME:-default}`` expansion."""

from __future__ import annotations

import re
from pathlib import Path

from pyfect import _js
from pyfect._core import Effect
from pyfect.config_provider._env import from_env_record
from pyfect.config_provider._node import SourceError
from pyfect.config_provider._provider import ConfigProvider
from pyfect.effect import try_blocking

# Effect's regexes with JavaScript's \s, ".", and multiline "^" / "$".
_S = f"[{_js.SPACE}]"
_START = f"(?:\\A|(?<=[{_js.LINE_END}]))"
_END = f"(?=[{_js.LINE_END}]|\\Z)"
_LINE = re.compile(
    rf"{_START}{_S}*(?:export{_S}+)?([A-Za-z0-9_.-]+)(?:{_S}*={_S}*?|:{_S}+?)"
    rf"({_S}*'(?:\\'|[^'])*'|{_S}*\"(?:\\\"|[^\"])*\"|{_S}*`(?:\\`|[^`])*`|[^#\r\n]+)?"
    rf"{_S}*(?:#[^{_js.LINE_END}]*)?{_END}"
)
_QUOTED = re.compile(rf"{_START}(['\"`])([\s\S]*)\1{_END}")
_REFERENCE = re.compile(r"\$\{?([A-Za-z0-9_]+)")


def from_dot_env_contents(
    contents: str, *, expand_variables: bool = False, preserve_empty_strings: bool = False
) -> ConfigProvider:
    """A provider over the ``NAME=value`` lines of a ``.env`` file, read as
    ``from_env_record`` reads them. ``#`` comments, ``export`` prefixes and
    single, double or backtick quotes are understood; ``\\n`` and ``\\r``
    are expanded inside double quotes. With ``expand_variables``, ``$NAME``,
    ``${NAME}`` and ``${NAME:-default}`` are replaced by other entries of the
    file (``\\$`` stays a literal ``$``)."""
    env = _parse(contents)
    if expand_variables:
        env = _expand(env)
    return from_env_record(env, preserve_empty_strings=preserve_empty_strings)


def from_dot_env(
    path: str | Path = ".env",
    *,
    expand_variables: bool = False,
    preserve_empty_strings: bool = False,
) -> Effect[ConfigProvider, SourceError]:
    """Read ``path`` (UTF-8, on a worker thread) and build
    ``from_dot_env_contents`` from it. A file that cannot be read fails with
    a ``SourceError`` whose ``cause`` is the ``OSError``."""
    return try_blocking(
        lambda: Path(path).read_text(encoding="utf-8"),
        lambda error: SourceError(f"Failed to read file at {path}", error),
    ).map(
        lambda contents: from_dot_env_contents(
            contents,
            expand_variables=expand_variables,
            preserve_empty_strings=preserve_empty_strings,
        )
    )


def _parse(contents: str) -> dict[str, str]:
    env: dict[str, str] = {}
    text = re.sub(r"\r\n?", "\n", contents)
    for match in _LINE.finditer(text):
        value = _js.trim(match.group(2) or "")
        quote = value[:1]
        value = _QUOTED.sub(r"\2", value)
        if quote == '"':
            value = value.replace("\\n", "\n").replace("\\r", "\r")
        env[match.group(1)] = value
    return env


def _expand(parsed: dict[str, str]) -> dict[str, str]:
    return {
        key: _interpolate(value, parsed, frozenset({key})).replace("\\$", "$")
        for key, value in parsed.items()
    }


def _interpolate(text: str, parsed: dict[str, str], seen: frozenset[str]) -> str:
    """Replace the references in ``text``. A reference already being
    expanded (a cycle, or a name referring to itself) expands to nothing;
    substituted values are not scanned again."""
    out: list[str] = []
    cursor = 0
    position = 0
    while (match := _REFERENCE.search(text, position)) is not None:
        start = match.start()
        position = match.end()
        if start > 0 and text[start - 1] == "\\":
            continue
        name = match.group(1)
        end = position
        default = ""
        if text.startswith(":-", end):
            end += 2
            default_start = end
            depth = 0
            # Match the default's braces in the source, not in substituted values.
            while end < len(text):
                if text.startswith("${", end):
                    depth += 1
                    end += 1
                elif text[end] == "}":
                    if depth == 0:
                        break
                    depth -= 1
                end += 1
            default = text[default_start:end]
        if text.startswith("}", end):
            end += 1
        expanded = (
            _interpolate(parsed[name], parsed, seen | {name})
            if name in parsed and name not in seen
            else ""
        )
        out.append(text[cursor:start])
        out.append(expanded or _interpolate(default, parsed, seen))
        cursor = end
        position = end
    out.append(text[cursor:])
    return "".join(out)
