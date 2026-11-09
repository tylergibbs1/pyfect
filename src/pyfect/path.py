"""Path operations as a service (Effect's ``Path``).

Programs that take the ``Path`` service instead of importing ``os.path``
can be run against another platform's rules (``layer_posix``,
``layer_win32``) or a test double::

    p = yield from Path()
    config = p.join(home, ".config", "app.toml")

``posix`` follows Node's ``path.posix``, as Effect does (``join("/a", "/b")``
is ``"/a/b"``, ``dirname("/a/b/")`` is ``"/a"``, ``relative`` of a path to
itself is ``""``). ``win32`` is ``ntpath``.
"""

from __future__ import annotations

import ntpath
import os
import posixpath
import re
from dataclasses import dataclass
from typing import Never, Protocol

from pyfect import _path_posix
from pyfect._core import Effect
from pyfect._url import Url
from pyfect._whatwg_url import _percent, setters
from pyfect.context import Tag
from pyfect.effect import fail, succeed
from pyfect.layer import Layer
from pyfect.layer import succeed as layer_succeed
from pyfect.platform_error import BadArgument


class _PathModule(Protocol):
    """The part of ``posixpath`` / ``ntpath`` the service uses."""

    @property
    def sep(self) -> str: ...
    def basename(self, p: str, /) -> str: ...
    def dirname(self, p: str, /) -> str: ...
    def splitext(self, p: str, /) -> tuple[str, str]: ...
    def splitroot(self, p: str, /) -> tuple[str, str, str]: ...
    def isabs(self, s: str, /) -> bool: ...
    def join(self, a: str, /, *paths: str) -> str: ...
    def normpath(self, path: str, /) -> str: ...
    def relpath(self, path: str, start: str | None = None) -> str: ...
    def abspath(self, path: str, /) -> str: ...


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


class PathService:
    """``Path`` over one ``os.path`` module (``posixpath`` or ``ntpath``)."""

    __slots__ = ("_m", "_windows")

    def __init__(self, module: _PathModule, *, windows: bool) -> None:
        self._m = module
        self._windows = windows

    @property
    def sep(self) -> str:
        return self._m.sep

    def basename(self, path: str, suffix: str = "") -> str:
        """The last part of ``path``, without ``suffix`` when it ends with
        it (and is more than it)."""
        base = self._m.basename(path)
        if suffix and base.endswith(suffix) and base != suffix:
            return base[: -len(suffix)]
        return base

    def dirname(self, path: str) -> str:
        return self._m.dirname(path)

    def extname(self, path: str) -> str:
        """The extension of the last part, dot included (``""`` for
        ``.bashrc``)."""
        return self._m.splitext(path)[1]

    def format(
        self, *, root: str = "", dir: str = "", base: str = "", name: str = "", ext: str = ""
    ) -> str:
        """Node's ``path.format``: ``dir`` (else ``root``), then ``base``
        (else ``name + ext``)."""
        directory = dir or root
        last = base or name + ext
        if not directory:
            return last
        if directory == root:
            return directory + last
        return directory + self.sep + last

    def from_file_url(self, url: Url) -> Effect[str, BadArgument]:
        """The path a ``file:`` URL names. Fails for another scheme, a host
        (but a Windows share), an encoded separator or a broken escape."""
        if url.protocol != "file:":
            return _bad_url("URL must be of scheme file")
        host = url.hostname
        if host and not self._windows:
            return _bad_url("Invalid file URL host")
        path = url.pathname
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
        return self._m.isabs(path)

    def join(self, *paths: str) -> str:
        return self._m.join(*paths) if paths else "."

    def normalize(self, path: str) -> str:
        return self._m.normpath(path)

    def parse(self, path: str) -> Parsed:
        drive, root, _tail = self._m.splitroot(path)
        base = self._m.basename(path)
        name, ext = self._m.splitext(base)
        return Parsed(root=drive + root, dir=self._m.dirname(path), base=base, ext=ext, name=name)

    def relative(self, from_: str, to: str) -> str:
        """The path from ``from_`` to ``to`` (``os.path.relpath``); ``to``
        made absolute when no relative path leads there (another drive)."""
        try:
            return self._m.relpath(to, from_)
        except ValueError:
            return self._m.abspath(to)

    def resolve(self, *segments: str) -> str:
        """The absolute path ``segments`` lead to from the working
        directory."""
        return self._m.abspath(self._m.join("", *segments))

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

    def to_file_url(self, path: str) -> Effect[Url, BadArgument]:
        """The ``file:`` URL of ``path``, made absolute first (a trailing
        separator kept); ``%``, ``\\``, tab and newlines are escaped."""
        resolved = self.resolve(path)
        host = ""
        if self._windows:
            resolved = resolved.replace("\\", "/")
            if resolved.startswith("//"):
                host, _, rest = resolved[2:].partition("/")
                resolved = "/" + rest
            else:
                resolved = "/" + resolved
        elif path.endswith("/") and not resolved.endswith("/"):
            resolved += "/"
        record = setters.set_pathname(Url("file://").record, _encode_path_chars(resolved))
        if host:
            record = setters.set_hostname(record, host)
        return succeed(Url.from_record(record))

    def to_namespaced_path(self, path: str) -> str:
        """Windows' ``\\\\?\\`` form of an absolute path; on POSIX, ``path``."""
        if not self._windows or not path:
            return path
        resolved = self.resolve(path)
        if resolved.startswith("\\\\?\\"):
            return resolved
        if resolved.startswith("\\\\"):
            return "\\\\?\\UNC\\" + resolved[2:]
        if re.match(r"[A-Za-z]:\\", resolved):
            return "\\\\?\\" + resolved
        return path


_PATH_CHAR_ESCAPES = str.maketrans({"%": "%25", "\\": "%5C", "\n": "%0A", "\r": "%0D", "\t": "%09"})


def _encode_path_chars(path: str) -> str:
    """Node's ``encodePathChars``: what the ``pathname`` setter would read
    as an escape, a separator or nothing."""
    return path.translate(_PATH_CHAR_ESCAPES)


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
    return _percent.decode(text).decode("utf-8", errors="strict")


class Path(Tag[PathService]):
    """The path rules a program uses."""


class _NodePosix(PathService):
    """The operations whose results differ between Node and ``posixpath``."""

    __slots__ = ()

    def basename(self, path: str, suffix: str = "") -> str:
        return _path_posix.basename(path, suffix)

    def dirname(self, path: str) -> str:
        return _path_posix.dirname(path)

    def extname(self, path: str) -> str:
        return _path_posix.extname(path)

    def join(self, *paths: str) -> str:
        return _path_posix.join(*paths)

    def normalize(self, path: str) -> str:
        return _path_posix.normalize(path)

    def parse(self, path: str) -> Parsed:
        root, directory, base, ext, name = _path_posix.parse(path)
        return Parsed(root=root, dir=directory, base=base, ext=ext, name=name)

    def relative(self, from_: str, to: str) -> str:
        return _path_posix.relative(from_, to)

    def resolve(self, *segments: str) -> str:
        return _path_posix.resolve(*segments)


posix: PathService = _NodePosix(posixpath, windows=False)
"""POSIX rules (Node's ``path.posix``)."""

win32 = PathService(ntpath, windows=True)
"""Windows rules (``ntpath``)."""

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
