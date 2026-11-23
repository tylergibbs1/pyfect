"""A matched request path with the values of a route's ``redacted_params`` hidden, as the
server span and the request log record it (Effect's ``http/internal/redactedPath``)."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import quote

from pyfect.http._url_text import strip_search_and_hash, to_path
from pyfect.http.find_my_way._paths import closing_parenthesis

if TYPE_CHECKING:
    from pyfect.http.server_request import ServerRequest

_STATIC = "s"
_PARAM = "p"
_REDACTED = "r"
_REDACTED_RUN = re.compile("r+")
_URI_SAFE = "-_.!~*'()"


@dataclass(frozen=True, slots=True)
class RedactedPath:
    """``kinds[i]`` says whether ``text[i]`` is static (``s``), a param (``p``) or
    redacted (``r``)."""

    text: str
    kinds: str


@dataclass(frozen=True, slots=True)
class _Param:
    name: str
    redacted: bool


type Template = tuple[str | _Param, ...]


def compile_template(path: str, redacted_params: Sequence[str]) -> Template:
    """The parts of a route path, its params marked redacted or not."""
    parts: list[str | _Param] = []
    # find-my-way gives regex captures to params in order, so a constraint without
    # exactly one capture shifts values onto the wrong names.
    ambiguous = False
    text = ""
    i = 0
    while i < len(path):
        char = path[i]
        if char == ":" and path[i + 1 : i + 2] == ":":
            text += ":"
            i += 2
            continue
        if char not in ":*":
            text += char
            i += 1
            continue
        end = i + 1
        if char == ":":
            while (
                end < len(path)
                and path[end] not in "(-./"
                and not (path[end] == "?" and (end == len(path) - 1 or path[end + 1] == "/"))
            ):
                end += 1
        name = "*" if char == "*" else path[i + 1 : end]
        if text:
            parts.append(text)
        text = ""
        parts.append(_Param(name, name in redacted_params))
        if char == "*":
            i += 1
            continue
        if path[end : end + 1] == "(":
            close = closing_parenthesis(path, end)
            ambiguous = ambiguous or _count_captures(path[end : close + 1]) != 1
            i = close + 1
        else:
            i = end + 1 if path[end : end + 1] == "?" else end
    if text:
        parts.append(text)
    if ambiguous:
        return tuple(part if isinstance(part, str) else _Param(part.name, True) for part in parts)
    return tuple(parts)


def _count_captures(regex: str) -> int:
    try:
        return re.compile(regex).groups
    except re.error:
        return -1


def render(template: Template, params: Mapping[str, str]) -> RedactedPath:
    """The path a route matched, from its template and the params it matched."""
    text = ""
    kinds = ""
    for part in template:
        if isinstance(part, str):
            text += part
            kinds += _STATIC * len(part)
            continue
        value = params.get(part.name)
        if value is None:
            # An absent optional param or wildcard is last and drops its whole segment.
            slash = max(text.rfind("/"), 0)
            text = text[:slash]
            kinds = kinds[:slash]
            break
        encoded = (
            "/".join(_encode_segment(s) for s in value.split("/"))
            if part.name == "*"
            else _encode_segment(value)
        )
        text += encoded
        kinds += (_REDACTED if part.redacted else _PARAM) * len(encoded)
    # A bare wildcard captures the leading slash, which stays visible.
    if text.startswith("/"):
        return RedactedPath(text, _STATIC + kinds[1:])
    return RedactedPath("/" + text, _STATIC + kinds)


def _encode_segment(segment: str) -> str:
    try:
        return quote(segment, safe=_URI_SAFE)
    except UnicodeEncodeError:
        return segment


def combine(
    previous: RedactedPath | None, next: RedactedPath, request: ServerRequest
) -> RedactedPath:
    """Merge a nested router's redacted path without weakening the outer one's."""
    if previous is None:
        # Restore the mount prefix removed from ``request.url``.
        local = strip_search_and_hash(request.url)
        original = to_path(request.original_url)
        if local == original or not original.endswith(local):
            return next
        prefix = original[: len(original) - len(local)]
        return RedactedPath(prefix + next.text, _PARAM * len(prefix) + next.kinds)
    if not previous.text.endswith(next.text):
        # The paths do not line up: redact every param.
        return RedactedPath(previous.text, previous.kinds.replace(_PARAM, _REDACTED))
    offset = len(previous.text) - len(next.text)
    kinds = previous.kinds[:offset] + "".join(
        _REDACTED if kind == _REDACTED else previous.kinds[offset + i]
        for i, kind in enumerate(next.kinds)
    )
    return RedactedPath(previous.text, kinds)


def format_path(path: RedactedPath) -> str:
    """The path with each run of redacted characters replaced by ``REDACTED``."""
    out = ""
    last = 0
    for run in _REDACTED_RUN.finditer(path.kinds):
        out += path.text[last : run.start()] + "REDACTED"
        last = run.end()
    return out + path.text[last:]
