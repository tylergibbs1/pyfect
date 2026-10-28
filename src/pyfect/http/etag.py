"""Entity tags (Effect's ``Etag``): ``Weak`` / ``Strong`` values and the
``Generator`` service that makes them for files."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar, Literal

from pyfect._core import Effect
from pyfect.context import Tag
from pyfect.effect import sync
from pyfect.file_system import FileInfo
from pyfect.http.file_like import FileLike
from pyfect.layer import Layer
from pyfect.layer import succeed as layer_succeed


@dataclass(frozen=True, slots=True)
class Weak:
    value: str
    tag: ClassVar[Literal["Weak"]] = "Weak"


@dataclass(frozen=True, slots=True)
class Strong:
    value: str
    tag: ClassVar[Literal["Strong"]] = "Strong"


type Etag = Weak | Strong


def to_string(etag: Etag) -> str:
    """The header value: ``W/"value"`` or ``"value"``."""
    match etag:
        case Weak(value):
            return f'W/"{value}"'
        case Strong(value):
            return f'"{value}"'


def _milliseconds(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def value_from_file_info(info: FileInfo) -> str:
    """``<size>-<mtime ms>`` in hex (``0`` without an mtime)."""
    mtime = "0" if info.mtime is None else format(_milliseconds(info.mtime), "x")
    return f"{int(info.size):x}-{mtime}"


def value_from_file_web(file: FileLike) -> str:
    return f"{file.size:x}-{_milliseconds(file.last_modified):x}"


@dataclass(frozen=True, slots=True)
class GeneratorService:
    """Makes the entity tag of a file: ``weak`` ones, or strong ones."""

    weak: bool

    def _make(self, value: str) -> Etag:
        return Weak(value) if self.weak else Strong(value)

    def from_file_info(self, info: FileInfo) -> Effect[Etag]:
        return sync(lambda: self._make(value_from_file_info(info)))

    def from_file_web(self, file: FileLike) -> Effect[Etag]:
        return sync(lambda: self._make(value_from_file_web(file)))


class Generator(Tag[GeneratorService], key="effect/http/Etag/Generator"):
    """The entity tag generator."""


layer: Layer[Generator] = layer_succeed(Generator, GeneratorService(weak=False))
"""Strong tags."""

layer_weak: Layer[Generator] = layer_succeed(Generator, GeneratorService(weak=True))
"""Weak tags."""

__all__ = [
    "Etag",
    "Generator",
    "GeneratorService",
    "Strong",
    "Weak",
    "layer",
    "layer_weak",
    "to_string",
    "value_from_file_info",
    "value_from_file_web",
]
