"""Path operations as a service (Effect's ``Path``).

Programs that take the ``Path`` service instead of importing ``os.path``
can be run against another platform's rules (``layer_posix``,
``layer_win32``) or a test double::

    p = yield from Path()
    config = p.join(home, ".config", "app.toml")

``posix`` and ``win32`` follow Node's ``path.posix`` and ``path.win32``, as
Effect does (``join("/a", "/b")`` is ``"/a/b"``, ``dirname("/a/b/")`` is
``"/a"``, ``relative`` of a path to itself is ``""``), on any host.
"""

from __future__ import annotations

import os
import re
import urllib.parse
from dataclasses import dataclass
from typing import Never, Protocol

from pyfect import _path_posix, _path_win32
from pyfect._core import Effect
from pyfect.context import Tag
from pyfect.effect import fail, succeed
from pyfect.layer import Layer
from pyfect.layer import succeed as layer_succeed
from pyfect.platform_error import BadArgument


class _Rules(Protocol):
    """One platform's path rules (``_path_posix``, ``_path_win32``): Node's ``path.posix`` or
    ``path.win32``."""

    sep: str
    delimiter: str

    def basename(self, path: str, suffix: str = "", /) -> str: ...
    def dirname(self, path: str, /) -> str: ...
    def extname(self, path: str, /) -> str: ...
    def is_absolute(self, path: str, /) -> bool: ...
    def join(self, *paths: str) -> str: ...
    def normalize(self, path: str, /) -> str: ...
    def parse(self, path: str, /) -> tuple[str, str, str, str, str]: ...
    def relative(self, from_: str, to: str, /) -> str: ...
    def resolve(self, *segments: str) -> str: ...
    def to_namespaced_path(self, path: str, /) -> str: ...


@dataclass(frozen=True, slots=True)
class Parsed:
    """The parts of a path (Node's ``path.parse``): ``/home/u/f.txt`` has
    root ``"/"``, dir ``"/home/u"``, base ``"f.txt"``, name ``"f"`` and ext
    ``".txt"``."""

    root: str = ""
    dir: str = ""
    base: str = ""
    ext: str = ""
    name: str = ""


_ENCODED_SEPARATOR = re.compile(r"%2f", re.IGNORECASE)
_ENCODED_BACKSLASH = re.compile(r"%5c", re.IGNORECASE)
_BAD_ESCAPE = re.compile(r"%(?![0-9A-Fa-f]{2})")
# WHATWG's path percent-encode set leaves these as they are.
_URL_SAFE = "/!$&'()*+,;=:@-._~"


class PathService:
    """``Path`` over one platform's rules."""

    __slots__ = ("_rules", "_windows")

    def __init__(self, rules: _Rules, *, windows: bool) -> None:
        self._rules = rules
        self._windows = windows

    @property
    def sep(self) -> str:
        return self._rules.sep

    @property
    def delimiter(self) -> str:
        """What separates paths in a list such as ``PATH`` (``:``, or ``;`` on Windows)."""
        return self._rules.delimiter

    def basename(self, path: str, suffix: str = "") -> str:
        """The last part of ``path``, without ``suffix`` when it ends with
        it (and is more than it)."""
        return self._rules.basename(path, suffix)

    def dirname(self, path: str) -> str:
        return self._rules.dirname(path)

    def extname(self, path: str) -> str:
        """The extension of the last part, dot included (``""`` for
        ``.bashrc``)."""
        return self._rules.extname(path)

    def format(
        self, *, root: str = "", dir: str = "", base: str = "", name: str = "", ext: str = ""
    ) -> str:
        """Node's ``path.format``: ``dir`` (else ``root``), then ``base``
        (else ``name`` and ``ext``, which gets a dot if it has none)."""
        directory = dir or root
        last = base or name + (ext if not ext or ext[0] == "." else "." + ext)
        if not directory:
            return last
        if directory == root:
            return directory + last
        return directory + self.sep + last

    def from_file_url(self, url: str) -> Effect[str, BadArgument]:
        """The path a ``file:`` URL names. Fails for another scheme, a host
        (but a Windows share), an encoded separator or a broken escape."""
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != "file":
            return _bad_url("URL must be of scheme file")
        host = parts.hostname or ""
        if host == "localhost":
            host = ""
        if host and not self._windows:
            return _bad_url("Invalid file URL host")
        path = _remove_dot_segments(parts.path)
        encoded = _ENCODED_SEPARATOR.search(path) or (
            self._windows and _ENCODED_BACKSLASH.search(path)
        )
        if encoded:
            return _bad_url("must not include encoded / characters")
        try:
            decoded = _decode_uri_component(path)
        except ValueError as error:
            return fail(BadArgument(module="Path", method="from_file_url", cause=error))
        return succeed(_windows_path(host, decoded) if self._windows else decoded)

    def is_absolute(self, path: str) -> bool:
        return self._rules.is_absolute(path)

    def join(self, *paths: str) -> str:
        return self._rules.join(*paths)

    def normalize(self, path: str) -> str:
        return self._rules.normalize(path)

    def parse(self, path: str) -> Parsed:
        return Parsed(*self._rules.parse(path))

    def relative(self, from_: str, to: str) -> str:
        """The path from ``from_`` to ``to``, both resolved first; ``to``
        resolved when no relative path leads there (another drive)."""
        return self._rules.relative(from_, to)

    def resolve(self, *segments: str) -> str:
        """The absolute path ``segments`` lead to from the working
        directory."""
        return self._rules.resolve(*segments)

    def resolve_within(self, root: str, input: str) -> str | None:
        """``input`` resolved below ``root``, or ``None`` when it is rooted
        or leads outside ``root`` (a ``..`` past it)."""
        if self.parse(input).root != "":
            return None
        base = self.resolve(root)
        candidate = self.resolve(base, input)
        relative = self.relative(base, candidate)
        if relative == ".." or relative.startswith(".." + self.sep) or self.is_absolute(relative):
            return None
        return candidate

    def to_file_url(self, path: str) -> Effect[str, BadArgument]:
        """The ``file:`` URL of ``path``, made absolute first."""
        resolved = self.resolve(path)
        if self._windows:
            resolved = resolved.replace("\\", "/")
            if resolved.startswith("//"):
                host, _, rest = resolved[2:].partition("/")
                return succeed(f"file://{host}/{urllib.parse.quote(rest, safe=_URL_SAFE)}")
            resolved = "/" + resolved
        elif path.endswith("/") and not resolved.endswith("/"):
            resolved += "/"
        return succeed("file://" + urllib.parse.quote(resolved, safe=_URL_SAFE))

    def to_namespaced_path(self, path: str) -> str:
        """Windows' ``\\\\?\\`` form of an absolute path; on POSIX, ``path``."""
        return self._rules.to_namespaced_path(path)


_SINGLE_DOT = frozenset((".", "%2e"))
_DOUBLE_DOT = frozenset(("..", ".%2e", "%2e.", "%2e%2e"))
_DRIVE = re.compile(r"[A-Za-z][:|]")


def _remove_dot_segments(path: str) -> str:
    """The WHATWG URL parser's handling of ``.`` and ``..`` segments (encoded
    dots included) in a ``file:`` URL's path; ``..`` never leaves a drive
    letter."""
    segments = path.split("/")[1:]
    kept: list[str] = []
    for index, segment in enumerate(segments):
        last = index == len(segments) - 1
        dots = segment.lower()
        if dots in _DOUBLE_DOT:
            if kept and not (len(kept) == 1 and _DRIVE.fullmatch(kept[0])):
                kept.pop()
            if last:
                kept.append("")
        elif dots in _SINGLE_DOT:
            if last:
                kept.append("")
        else:
            kept.append(segment)
    return "/" + "/".join(kept) if segments else path


def _windows_path(host: str, decoded: str) -> str:
    path = decoded.replace("/", "\\")
    if host:
        return f"\\\\{host}{path}"
    return path[1:] if re.match(r"\\[A-Za-z]:", path) else path


def _bad_url(description: str) -> Effect[Never, BadArgument]:
    return fail(BadArgument(module="Path", method="from_file_url", description=description))


def _decode_uri_component(text: str) -> str:
    """JavaScript's ``decodeURIComponent``: a ``%`` without two hex digits,
    or escapes that are not UTF-8, raise ``ValueError``."""
    if _BAD_ESCAPE.search(text):
        raise ValueError(f"URI malformed: {text}")
    return urllib.parse.unquote_to_bytes(text).decode("utf-8", errors="strict")


class Path(Tag[PathService]):
    """The path rules a program uses."""


posix = PathService(_path_posix, windows=False)
"""POSIX rules (Node's ``path.posix``)."""

win32 = PathService(_path_win32, windows=True)
"""Windows rules (Node's ``path.win32``), the same on any host."""

layer_posix: Layer[Path] = layer_succeed(Path, posix)
layer_win32: Layer[Path] = layer_succeed(Path, win32)
layer: Layer[Path] = layer_win32 if os.name == "nt" else layer_posix
"""The host's rules."""

__all__ = [
    "BadArgument",
    "Parsed",
    "Path",
    "PathService",
    "layer",
    "layer_posix",
    "layer_win32",
    "posix",
    "win32",
]
