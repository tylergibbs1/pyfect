"""What a provider finds at a path: the ``Node`` shapes, the path type and
``SourceError``."""

from __future__ import annotations

from dataclasses import dataclass

from pyfect.errors import TaggedError

type Segment = str | int
"""A path segment: a record key or an array index."""

type Path = tuple[Segment, ...]
"""A lookup path, outermost segment first."""

type PathInput = tuple[Segment, ...] | list[Segment]
"""What ``load`` and ``map_input`` functions accept: a tuple or a list (never
a bare string, which would be read as one segment per character)."""


@dataclass(frozen=True, slots=True)
class Value:
    """A terminal string value."""

    value: str


@dataclass(frozen=True, slots=True)
class Record:
    """An object. ``keys`` are its child names; ``value`` is a string stored
    at the same path (an env var ``A`` next to ``A_B``), if any."""

    keys: frozenset[str]
    value: str | None = None


@dataclass(frozen=True, slots=True)
class Array:
    """An array-like container of ``length`` elements; ``value`` is a string
    stored at the same path, if any."""

    length: int
    value: str | None = None

    def __post_init__(self) -> None:
        if self.length < 0:
            raise ValueError(f"Array length must be >= 0, got {self.length}")


type Node = Value | Record | Array


@dataclass(eq=False)
class SourceError(TaggedError):
    """The source behind a provider could not be read (as opposed to a path
    that is simply absent, which ``load`` reports as ``None``)."""

    message: str
    cause: object = None


def to_path(path: PathInput) -> Path:
    return path if isinstance(path, tuple) else tuple(path)
