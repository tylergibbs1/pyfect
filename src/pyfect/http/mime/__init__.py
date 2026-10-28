"""MIME types of file names, and file extensions of MIME types (Effect's
``Mime``), from the standard table of the ``mime`` package::

    get_type("index.html")          # "text/html"
    get_extension("text/html")      # "html"
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache

from pyfect.http.mime._types import TYPES


@dataclass(frozen=True, slots=True)
class _Tables:
    extension_to_type: dict[str, str]
    type_to_extension: dict[str, str]
    type_to_extensions: dict[str, frozenset[str]]


@cache
def _tables() -> _Tables:
    extension_to_type: dict[str, str] = {}
    type_to_extension: dict[str, str] = {}
    type_to_extensions: dict[str, frozenset[str]] = {}
    for mime_type, extensions in TYPES.items():
        names = [extension.removeprefix("*") for extension in extensions]
        type_to_extensions[mime_type] = frozenset(names)
        type_to_extension[mime_type] = names[0]
        for extension, name in zip(extensions, names, strict=True):
            if not extension.startswith("*"):
                extension_to_type[name] = mime_type
    return _Tables(extension_to_type, type_to_extension, type_to_extensions)


_DIRECTORY = re.compile(r"^.*[/\\]", re.DOTALL)
_STEM = re.compile(r"^.*\.", re.DOTALL)


def get_type(path: str) -> str | None:
    """The MIME type of the file name or path's extension (any case), or
    ``None`` for an unknown one or a path without an extension."""
    last = _DIRECTORY.sub("", path, count=1).lower()
    extension = _STEM.sub("", last, count=1)
    has_path = len(last) < len(path)
    has_dot = len(extension) < len(last) - 1
    if not has_dot and has_path:
        return None
    return _tables().extension_to_type.get(extension)


def _essence(mime_type: str) -> str:
    return mime_type.split(";", 1)[0].strip().lower()


def get_extension(mime_type: str) -> str | None:
    """The usual extension of ``mime_type`` (parameters ignored)."""
    return _tables().type_to_extension.get(_essence(mime_type))


def get_all_extensions(mime_type: str) -> frozenset[str] | None:
    """Every extension of ``mime_type`` (parameters ignored)."""
    return _tables().type_to_extensions.get(_essence(mime_type))


__all__ = ["get_all_extensions", "get_extension", "get_type"]
