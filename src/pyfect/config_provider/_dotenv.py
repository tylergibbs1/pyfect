"""``.env`` files: Effect's parser (the ``dotenv`` package's rules) and its
``dotenv-expand``-style ``$NAME`` / ``${NAME:-default}`` expansion."""

from __future__ import annotations

import os
import re
from collections.abc import Iterator

from pyfect import _js
from pyfect._core import Effect
from pyfect.config_provider._env import from_env_record
from pyfect.config_provider._provider import ConfigProvider
from pyfect.file_system import FileSystem
from pyfect.platform_error import PlatformError

# Effect's regexes with JavaScript's \s, ".", and multiline "^" / "$".
_S = f"[{_js.SPACE}]"
_START = f"(?:\\A|(?<=[{_js.LINE_END}]))"
_END = f"(?=[{_js.LINE_END}]|\\Z)"
_AFTER = f"{_S}*(?:[{_js.LINE_END}#]|\\Z)"
"""What may follow a value: spaces, then a line end, a comment or the end."""


def _quoted(quote: str) -> str:
    """Effect's ``\\s*'(?:\\\\'|[^'])*'`` for ``quote``, without backtracking.

    A quote after a backslash may close the value or belong to it; Effect's pattern closes
    at the last such quote, before the first one after no backslash, that ``_AFTER`` accepts.
    Here an escaped quote is passed only while a later one (or the unescaped one) is
    accepted, so ``re`` keeps no frame per character."""
    escaped = rf"(?<=\\){quote}"
    later = rf"(?=(?:[^{quote}]++|{escaped}(?!{_AFTER}))*+{quote}(?={_AFTER}))"
    return rf"{_S}*{quote}(?:[^{quote}]++|{escaped}(?:(?!{_AFTER})|{later}))*+{quote}"


_LINE = re.compile(
    rf"{_START}{_S}*(?:export{_S}+)?([A-Za-z0-9_.-]+)(?:{_S}*={_S}*?|:{_S}+?)"
    rf"({_quoted("'")}|{_quoted('"')}|{_quoted('`')}|[^#\r\n]+)?"
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
    path: str | os.PathLike[str] = ".env",
    *,
    expand_variables: bool = False,
    preserve_empty_strings: bool = False,
) -> Effect[ConfigProvider, PlatformError, FileSystem]:
    """Read ``path`` with the ``FileSystem`` service and build
    ``from_dot_env_contents`` from it; a file that cannot be read fails
    with the file system's ``PlatformError``."""
    file = os.fspath(path)
    return FileSystem().flat_map(
        lambda fs: fs.read_file_string(file).map(
            lambda contents: from_dot_env_contents(
                contents,
                expand_variables=expand_variables,
                preserve_empty_strings=preserve_empty_strings,
            )
        )
    )


_SPACES = re.compile(f"{_S}*")
_LINE_STARTS = re.compile(f"(?<=[{_js.LINE_END}])")


def _lines(text: str) -> Iterator[re.Match[str]]:
    """``_LINE.finditer(text)``, without trying each line start of a whitespace run.

    ``_LINE`` begins by skipping whitespace, line ends included, so a line start inside a
    run fails wherever an earlier one in the run failed: what follows the skipped spaces is
    the same. ``finditer`` read the rest of the run from each one."""
    at = 0
    while True:
        match = _LINE.match(text, at)
        if match is not None:
            yield match
            at = match.end()
            continue
        if at == 0 or text[at - 1] in _js.LINE_END:
            at = next(_SPACES.finditer(text, at)).end()  # the run's end: it matches here
        if at >= len(text):
            return
        start = _LINE_STARTS.search(text, at + 1)
        if start is None:
            return
        at = start.start()


def _parse(contents: str) -> dict[str, str]:
    env: dict[str, str] = {}
    text = re.sub(r"\r\n?", "\n", contents)
    for match in _lines(text):
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
